"""Translate structured vendor prices into new-api billing expressions.

``pricing.json`` records list prices as numbers so they can be audited against
the vendor page. new-api bills exclusively through ``billingexpr``, where the
expression alone is the billing contract: token coefficients are real USD per
1M tokens, and no ratio conversion happens anywhere. This module is the single
place that turns one into the other, so a price change never requires hand
editing an expression.

Anything that cannot be expressed with the engine's variables is reported in
``unexpressible`` instead of being silently dropped.
"""

from decimal import Decimal

# DeepSeek peak window: Monday to Friday, 09:00-12:00 and 14:00-18:00 Beijing
# time. Public holidays are not known in advance and bill at peak.
PEAK_TERM = (
    'weekday("Asia/Shanghai") >= 1 && weekday("Asia/Shanghai") <= 5 && '
    '((hour("Asia/Shanghai") >= 9 && hour("Asia/Shanghai") < 12) || '
    '(hour("Asia/Shanghai") >= 14 && hour("Asia/Shanghai") < 18))'
)

# Token price field -> expression variable. ``output_text``/``output_image``
# split the output side, everything else has an unambiguous token variable.
TOKEN_VARIABLES = (
    ("input", "p"),
    ("output", "c"),
    ("output_text", "c"),
    ("output_image", "img_o"),
    ("cache_read", "cr"),
    ("cache_read_image", "img_cr"),
    ("cache_write", "cc"),
    ("cache_write_1h", "cc1h"),
    ("input_image", "img"),
)


def number(value):
    """Render a price without exponent notation or trailing zeros."""
    text = format(Decimal(str(value)).normalize(), "f")
    return "0" if text in ("-0", "") else text


def token_terms(price):
    """Build ``p * 2 + c * 8`` style terms for every priced token field.

    ``output`` is the aggregate output price; when the vendor splits text and
    image output the split fields replace it, otherwise the same tokens would
    be charged twice.
    """
    fields = dict(TOKEN_VARIABLES)
    if price.get("output") is not None and (
        price.get("output_text") is not None or price.get("output_image") is not None
    ):
        # ``output`` is the aggregate output price; the split fields carry the
        # same tokens, so keeping both would charge them twice. ``input`` is not
        # an aggregate: the engine subtracts ``img`` from ``p`` on its own.
        fields.pop("output")
    terms = []
    for field, variable in TOKEN_VARIABLES:
        if field not in fields:
            continue
        value = price.get(field)
        if value is None:
            continue
        terms.append(f"{variable} * {number(value)}")
    return terms


def token_expr(price, tier_name="standard"):
    terms = token_terms(price)
    if not terms:
        return None
    return f'tier("{tier_name}", ' + " + ".join(terms) + ")"


def _tier_boundaries(tiers):
    """Ascending list of (prompt_tokens_at_least, tier dict)."""
    usable = [
        (int(tier["prompt_tokens_at_least"]), tier)
        for tier in tiers or []
        if tier.get("prompt_tokens_at_least") is not None
    ]
    return sorted(usable, key=lambda item: item[0])


def _tier_name(index):
    if index == 0:
        return "standard"
    if index == 1:
        return "long_context"
    return f"long_context_{index}"


def length_tier_expr(row):
    """Nest ``tier()`` leaves on ``len`` boundaries.

    ``len`` is the full input context, so cache hits cannot push a request into
    a cheaper tier. The vendor applies the higher price to the whole request,
    which is what a flat branch switch reproduces.
    """
    if not row.get("tiers"):
        return None
    boundaries = _tier_boundaries(row.get("tiers"))
    if not boundaries:
        return None
    prices = [row] + [tier for _threshold, tier in boundaries]
    thresholds = [threshold for threshold, _tier in boundaries]
    leaves = []
    for index, price in enumerate(prices):
        leaf = token_expr(price, _tier_name(index))
        if leaf is None:
            return None
        leaves.append(leaf)
    expr = leaves[-1]
    for index in range(len(thresholds) - 1, -1, -1):
        expr = f"len <= {thresholds[index]} ? {leaves[index]} : {expr}"
    return expr


def time_tier_expr(row):
    """``<peak window> ? tier("peak", ...) : tier("off_peak", ...)``.

    Only the named rule ``deepseek_peak`` is translated. The window is part of
    the rule, not of the data, so an unknown rule is reported instead of being
    billed at peak around the clock.
    """
    time_tiers = row.get("time_tiers") or {}
    if time_tiers.get("rule") != "deepseek_peak":
        return None
    peak = time_tiers.get("peak")
    if not peak:
        return None
    off_peak = time_tiers.get("off_peak")
    if off_peak is None:
        multiplier = time_tiers.get("off_peak_multiplier")
        if multiplier is None:
            return None
        off_peak = {}
        for field, _variable in TOKEN_VARIABLES:
            value = peak.get(field)
            if value is not None:
                off_peak[field] = value * multiplier
    peak_expr = token_expr(peak, "peak")
    off_expr = token_expr(off_peak, "off_peak")
    if peak_expr is None or off_expr is None:
        return None
    return f"{PEAK_TERM} ? {peak_expr} : {off_expr}"


# Request fields the gateway actually lets an expression read. A meter keyed on
# anything else (Gemini's ``resolution``, for example) has no probe path, so
# guessing one would silently bill the wrong tier.
KNOWN_PROBES = {"quality", "size"}


def _meter_condition(when):
    """Translate a meter's ``when`` map into a request probe."""
    if not when:
        return None
    parts = []
    for key, value in when.items():
        if key not in KNOWN_PROBES:
            return None
        parts.append(f'param("{key}") == "{value}"')
    return " && ".join(parts)


def _default_meter(outputs):
    """Pick the tier a request gets when it names no size."""
    for meter in outputs:
        when = meter.get("when") or {}
        if when.get("quality") == "high" or when.get("resolution") == "1K":
            return meter
    return outputs[0]


def image_meter_expr(row):
    """Expression over per-image output prices.

    ``image_count`` is the settled request quantity, so the price stays a real
    USD amount instead of a token coefficient. Tiers whose condition the
    gateway cannot observe are reported, never guessed: an unmatched branch
    would keep billing the cheap tier for an expensive request.
    """
    meters = [m for m in row.get("meters") or [] if m.get("unit") == "image"]
    outputs = [m for m in meters if m.get("dim") == "output_image"]
    if not outputs:
        return None, []
    skipped = [
        f"input_image x {number(m['price'])} (no input-image-count variable)"
        for m in meters
        if m.get("dim") == "input_image"
    ]

    if all(set(m.get("when") or {}) <= KNOWN_PROBES for m in outputs):
        default = _default_meter(outputs)
        expr = f'tier("image", fixed({number(default["price"])})) * image_count'
        for index, meter in enumerate(reversed(outputs)):
            condition = _meter_condition(meter.get("when"))
            if condition is None:
                continue
            name = f"image_{len(outputs) - index}"
            expr = (
                f'{condition} ? tier("{name}", fixed({number(meter["price"])}))'
                f" * image_count : {expr}"
            )
        return expr, skipped

    for meter in outputs:
        for key, value in (meter.get("when") or {}).items():
            if key not in KNOWN_PROBES:
                skipped.append(
                    f"output_image {key}={value} x {number(meter['price'])}"
                    f" (gateway exposes no {key!r} request field)"
                )
    default = _default_meter(outputs)
    return f'tier("image", fixed({number(default["price"])})) * image_count', skipped


# 价格分两层维护：
#   官方价  api/newapi/pricing.json（公开，厂商官方页抄录）
#   自己的价 billing_basis（私有，只写「与官方不同」的字段）
# 合并规则是**字段级覆盖**：自己的价写了某个字段就覆盖，没写就继承官方。
OVERRIDE_FIELDS = (
    "input",
    "output",
    "output_text",
    "output_image",
    "cache_read",
    "cache_read_image",
    "cache_write",
    "cache_write_1h",
    "cache_write_12h",
    "input_image",
    "tiers",
    "meters",
    "per_image",
)
# 计价形态：自己的价一旦改成按张 / 按次，官方的 token 价整套都不再适用。
SHAPE_FIELDS = ("per_image", "meters")
# 官方档位是按官方基础价算的；我们只改基础价时若继承档位，超阈值就会按官方原价收。
TIER_FIELDS = ("tiers", "time_tiers")
TOKEN_PRICE_FIELDS = (
    "input",
    "output",
    "output_text",
    "output_image",
    "cache_read",
    "cache_read_image",
    "cache_write",
    "cache_write_1h",
    "cache_write_12h",
    "input_image",
)


def apply_billing_basis(row):
    """Overlay ``billing_basis``（自己的价）onto the official price row.

    字段级覆盖：自己的价里写了哪个字段就覆盖哪个，没写的继承官方价。
    两个例外：

    * 计价形态变了（自己的价是按张 / meters）：官方的 token 价与档位整体不适用；
    * 只改了基础价、没给自己的档位：不继承官方档位（档位基于官方基础价，
      混用会在阈值以上按官方原价收费）。

    没有 ``billing_basis`` 的行原样返回，即纯官方价。
    """
    own = row.get("billing_basis")
    if not isinstance(own, dict):
        return row

    merged = dict(row)
    if any(own.get(field) is not None for field in SHAPE_FIELDS):
        for field in OVERRIDE_FIELDS + TIER_FIELDS:
            merged.pop(field, None)
    elif any(own.get(field) is not None for field in TOKEN_PRICE_FIELDS):
        for field in TIER_FIELDS:
            if own.get(field) is None:
                merged.pop(field, None)

    for field in OVERRIDE_FIELDS:
        if own.get(field) is not None:
            merged[field] = own[field]
    return merged


def build(row):
    """Return ``(expression, unexpressible_items)`` for one price row.

    Token prices come first because the engine settles images through token
    variables too: the images endpoint reports output image tokens, so
    ``output_image`` becomes ``img_o`` and no per-image ``fixed()`` amount is
    needed. ``meters`` only describes quantities the engine cannot bill, and is
    reported rather than turned into a wrong expression.
    """
    row = apply_billing_basis(row)
    if row.get("price_kind") == "free":
        return 'tier("free", p * 0 + c * 0)', []

    timed = time_tier_expr(row)
    if timed:
        return timed, []

    tiers = length_tier_expr(row)
    if tiers:
        return tiers, []

    flat = token_expr(row)
    if flat:
        return flat, []

    if row.get("per_image") is not None or any(
        m.get("dim") == "output_image" for m in row.get("meters") or []
    ):
        return image_meter_expr(row)

    return None, []
