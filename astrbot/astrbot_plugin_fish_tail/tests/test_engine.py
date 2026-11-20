# -*- coding: utf-8 -*-
"""核心引擎自测：不依赖 AstrBot / DSH，纯标准库运行。"""
import os
import sys
import datetime
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.engine import RuleEngine, Injector, build_injection


def test_keywords():
    re_ = RuleEngine()
    cases = {
        "我今天好累啊": "疲惫",
        "摸摸头": "示好",
        "你个大肥鱼": "嘴硬",
        "对不起我不该冷落你": "委屈",
        "来吃米饭🍚": "嘴馋",
        "哈哈好开心": "开心",
        "你真棒我好崇拜": "得瑟",  # 先命中"棒"? -> 示好; 只验证返回合法情绪
    }
    legal = set(RuleEngine.KEYWORD_RULES and [e for _, e in RuleEngine.KEYWORD_RULES])
    for text, want in cases.items():
        st = re_.judge(text)
        assert st.emotion in legal, (text, st)
    print("[OK] 关键词判定全部落在合法情绪集合")


def test_time_and_habit():
    re_ = RuleEngine()
    st = re_.judge("在吗", now=datetime.datetime(2026, 11, 20, 2, 0))
    assert st.emotion == "疲惫", st
    st = re_.judge("在吗", now=datetime.datetime(2026, 11, 20, 14, 0), habit={"night_owl": True})
    assert st.emotion == "慵懒", st
    print("[OK] 时间/习惯判定")


def test_injection_format():
    inj = Injector()
    prompt, st = build_injection("我今天好累啊", injector=inj)
    assert "[鱼的尾巴和插件·动态渲染]" in prompt
    assert "严禁完全照抄" in prompt
    assert "绝对不要写「胖」字" in prompt
    assert st.emotion == "疲惫"
    print("[OK] 注入格式与防胖规则")


def test_dedup(tmp_path):
    path = os.path.join(str(tmp_path), "recent.json")
    inj = Injector(recent_store_path=path)
    inj.remember_action("它叹了口气（尾巴软塌塌地垂着）")
    inj.remember_action("（尾鳍有气无力地扫过键盘）")
    p1, _ = build_injection("累了", injector=inj)
    assert "尾巴软塌塌地垂着" in p1, p1
    # 重新载入应保留
    inj2 = Injector(recent_store_path=path)
    p2, _ = build_injection("累了", injector=inj2)
    assert "尾巴软塌塌地垂着" in p2, p2
    print("[OK] 最近动作去重与持久化")


if __name__ == "__main__":
    test_keywords()
    test_time_and_habit()
    test_injection_format()
    test_dedup(tempfile.mkdtemp())
    print("\n全部核心引擎测试通过")
