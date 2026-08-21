# -*- coding: utf-8 -*-
"""SysCenter 技能运行时（B 路：可执行技能）。

两层技能：
- 内置技能（代码内嵌，如天气查询）：直接注册，EXE 打包无歧义。
- 目录技能（可执行技能包，未来从 URL 下载安装）：扫描 <DATA_DIR>/skills，动态加载。

目录技能包格式：每个技能一个子目录，含
- skill.yaml：{name, description, trigger_keywords}
- handler.py：class SkillHandler，async execute(message, context, user_id=None) -> str
"""
from .loader import SkillRegistry, get_registry, init_skills

__all__ = ["SkillRegistry", "get_registry", "init_skills"]
