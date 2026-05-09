"""
credential_vault.py — 凭据隔离保管箱（防线 2）

核心原则：secret 不进 LLM context。
LLM 只看到引用 ID（如 $SECRET_0），工具执行前才解析为真实值。
"""

import re


class CredentialVault:
    """
    凭据保管箱：secret 通过引用 ID 间接传递，真实值只在工具执行瞬间暴露。

    使用流程：
        vault = CredentialVault()
        ref = vault.store("GITHUB_TOKEN", os.environ["GITHUB_TOKEN"])
        # ref = "$SECRET_0"，可以安全传入 LLM context
        # 工具调用前解析：
        cmd = vault.resolve("git push -H $SECRET_0")
        # cmd = "git push -H ghp_xxx..."（只有工具看到真实值）
    """

    def __init__(self):
        self._vault: dict[str, str] = {}   # ref_id -> 真实 secret

    def store(self, name: str, value: str) -> str:
        """
        存入 secret，返回引用 ID。
        引用 ID 可以安全出现在 LLM context 里。
        """
        # 用序号而非 name 作为 key，防止 name 本身泄露信息
        ref_id = f"$SECRET_{len(self._vault)}"
        self._vault[ref_id] = value
        # 记录 name 到 ref 的映射（方便按名查询），但不暴露 value
        print(f"[CredentialVault] stored '{name}' as {ref_id}")
        return ref_id

    def resolve(self, text: str) -> str:
        """
        工具执行前，将文本中的 $SECRET_N 替换为真实值。
        只有工具层调用此方法，LLM 永远只看到 $SECRET_N。
        """
        for ref_id, secret in self._vault.items():
            text = text.replace(ref_id, secret)
        return text

    def resolve_dict(self, args: dict) -> dict:
        """对工具参数字典中的所有字符串值执行解析。"""
        return {
            k: self.resolve(v) if isinstance(v, str) else v
            for k, v in args.items()
        }

    def clear(self):
        """任务结束后清除所有凭证（对应防线 2 的时间最小化规则）。"""
        count = len(self._vault)
        self._vault.clear()
        print(f"[CredentialVault] cleared {count} secret(s)")

    def has_secret_refs(self, text: str) -> bool:
        """检查文本中是否包含未解析的引用（用于审计）。"""
        return bool(re.search(r"\$SECRET_\d+", text))

    @property
    def ref_count(self) -> int:
        return len(self._vault)
