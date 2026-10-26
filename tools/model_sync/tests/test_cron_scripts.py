"""运维脚本权限的回归测试。

2026-10-26 起仓库里已没有 `tools/ops/*.sh`（全部改为手工流程），这组测试留着
防回归：将来若再加 shell 脚本被 cron/计划任务调用，权限位必须正确。

2026-10-26 起仓库里已没有 `tools/ops/*.sh`（全部改手工流程），这组测试留着防回归。

背景：`cron-promote-upcoming.sh`（已删除）曾以 100644 提交。Windows 上 `ls -l` 显示
`-rwxr-xr-x`（MSYS 不读该位），Linux checkout 后变成 `-rw-r--r--`，
crontab 直接执行该路径 → `Permission denied`，而它负责把到期的新价提升为当前价。
失败是静默的：cron 只在日志里留一句，没有告警。

所以校验必须查 **git index 的 mode**（跨平台一致），而不是 `os.access`（Windows 恒真）。
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tools.model_sync import validate as vd  # noqa: E402


class CronScriptModeTest(unittest.TestCase):
    def test_repo_scripts_are_executable_in_git(self):
        report = vd.Report()
        vd.check_cron_scripts(report)
        self.assertEqual(report.errors, [], "tools/ops 下的 .sh 必须提交为 100755")

    def test_missing_exec_bit_is_reported(self):
        report = vd.Report()
        vd.verify_script_modes(report, "100644 abc123 0\ttools/ops/example.sh\n")
        self.assertEqual(len(report.errors), 1)
        self.assertIn("100644", report.errors[0])
        self.assertIn("chmod=+x", report.errors[0])

    def test_executable_script_is_accepted(self):
        report = vd.Report()
        vd.verify_script_modes(report, "100755 abc123 0\ttools/ops/example.sh\n")
        self.assertEqual(report.errors, [])

    def test_non_git_environment_is_skipped(self):
        real_run = vd.subprocess.run

        def boom(*a, **kw):
            raise OSError("git not found")

        vd.subprocess.run = boom
        try:
            report = vd.Report()
            vd.check_cron_scripts(report)
        finally:
            vd.subprocess.run = real_run

        self.assertEqual(report.errors, [])


if __name__ == "__main__":
    unittest.main()
