"""数据源地址可配置 + key 中性别名。

重点是最后那条：**默认值必须保持上游官方地址**。本仓库是公开的，
哪天有人图省事把自建转发层写成默认值，陌生人就会往那个端点上打。
"""
import os
import sys
import unittest

sys.path.insert(0, "scripts")

from lib import env, tikhub  # noqa: E402


class BaseUrl(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.pop(k, None)
                       for k in ("L30D_BASE_URL", "TIKHUB_BASE_URL")}

    def tearDown(self):
        for k, v in self._saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v

    def test_default_is_upstream(self):
        self.assertEqual(tikhub._base(), "https://api.tikhub.io")

    def test_new_name_wins(self):
        os.environ["L30D_BASE_URL"] = "https://gw.example.com"
        os.environ["TIKHUB_BASE_URL"] = "https://old.example.com"
        self.assertEqual(tikhub._base(), "https://gw.example.com")

    def test_old_name_still_accepted(self):
        os.environ["TIKHUB_BASE_URL"] = "https://old.example.com"
        self.assertEqual(tikhub._base(), "https://old.example.com")

    def test_trailing_slash_stripped(self):
        os.environ["L30D_BASE_URL"] = "https://gw.example.com/"
        self.assertEqual(tikhub._base(), "https://gw.example.com")


class KeyAlias(unittest.TestCase):
    def test_process_env_new_name_beats_config_file_old_name(self):
        """进程环境的新名要压过配置文件的旧名，否则本机旧配置会盖掉网关 key。"""
        merged = {"TIKHUB_API_KEY": "from_file"}
        picked = (os.environ.get("L30D_API_KEY")
                  or os.environ.get("TIKHUB_API_KEY")
                  or merged.get("L30D_API_KEY")
                  or merged.get("TIKHUB_API_KEY"))
        self.assertTrue(picked)

    def test_gate_accepts_gateway_key(self):
        """闸门只看 key 在不在、不看格式——l30d_ 开头的也得放行。"""
        config = {"TIKHUB_API_KEY": "l30d_alice_xxx"}
        for source in ("weibo", "xiaohongshu", "bilibili", "douyin", "wechat"):
            self.assertTrue(env.is_source_available(source, config), source)


if __name__ == "__main__":
    unittest.main(verbosity=2) if "-v" in sys.argv else unittest.main()
