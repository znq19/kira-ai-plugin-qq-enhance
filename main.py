import asyncio

from core.plugin import BasePlugin, PluginContext, logger, on, Priority, register
from core.chat.message_utils import KiraMessageBatchEvent
from core.provider import LLMRequest

from core.utils.tool_utils import BaseTool


class SetEmojiTool(BaseTool):
    name = "set_qq_emoji"
    description = "给QQ消息贴表情"
    parameters = {
        "type": "object",
        "properties": {
            "message_id": {"type": "string", "description": "QQ消息ID"},
            "emoji_id": {"type": "string", "description": "表情ID，和<emoji>标签的表情ID相同"}
        },
        "required": ["message_id", "emoji_id"]
    }

    def __init__(self, ctx: PluginContext):
        super().__init__(ctx=ctx)

    async def execute(self, event: KiraMessageBatchEvent, *args, message_id: str, emoji_id: str, **kwargs) -> str:
        ada_name = event.session.adapter_name
        ada = self.ctx.adapter_mgr.get_adapter(ada_name)
        client = ada.get_client()
        params = {
            "message_id": message_id,
            "emoji_id": emoji_id
        }
        res = await client.send_action("set_msg_emoji_like", params)
        return res


class SendQQLikesTool(BaseTool):
    name = "send_qq_likes"
    description = "给QQ用户资料卡点赞"
    parameters = {
        "type": "object",
        "properties": {
            "qq": {"type": "string", "description": "QQ账号"},
            "times": {"type": "integer", "description": "点赞次数，默认为最大可点赞数，除非用户要求，否则无需改动"}
        },
        "required": ["qq"]
    }

    def __init__(self, ctx: PluginContext):
        super().__init__(ctx=ctx)

    async def execute(self, event: KiraMessageBatchEvent, *args, qq: str, times: int = 50, **kwargs) -> str:
        ada_name = event.session.adapter_name
        ada = self.ctx.adapter_mgr.get_adapter(ada_name)
        client = ada.get_client()
        if not client:
            return "点赞失败，未找到当前QQ适配器客户端"

        chunks = [10] * (times // 10) + ([times % 10] if times % 10 else [])
        state = {"likes_count": 0, "fail_msg": ""}
        try:
            await asyncio.wait_for(self._do_send_likes(client, qq, chunks, state), timeout=15)
        except asyncio.TimeoutError:
            return "点赞超时" + (f"（已点赞 {state['likes_count']} 次）" if state['likes_count'] else "")
        if state["fail_msg"]:
            return f"点赞失败：{state['fail_msg']}" + (f"（已点赞 {state['likes_count']} 次）" if state['likes_count'] else "")
        return f"点赞成功，点了 {state['likes_count']} 个赞"

    @staticmethod
    async def _do_send_likes(client, qq: str, chunks: list[int], state: dict) -> None:
        for chunk in chunks:
            resp = await client.send_action("send_like", {"user_id": qq, "times": chunk})
            if resp.get("status") != "ok":
                state["fail_msg"] = resp.get("message", "未知错误")
                return
            state["likes_count"] += chunk
            await asyncio.sleep(0.1)


class QQEnhancePlugin(BasePlugin):
    def __init__(self, ctx, cfg: dict):
        super().__init__(ctx, cfg)
        self.emoji_react_enabled = self.plugin_cfg.get("emoji_react_enabled", True)
        self.send_likes_enabled = self.plugin_cfg.get("send_likes_enabled", False)
        self.emoji_react_prompt = self.plugin_cfg.get("emoji_react_prompt", "")
    
    async def initialize(self):
        pass
    
    async def terminate(self):
        pass

    @on.llm_request()
    async def inject_qq_enhance_tools(self, event: KiraMessageBatchEvent, req: LLMRequest, *_):
        platform = event.adapter.platform
        if not platform == "QQ":
            return

        if self.emoji_react_enabled:
            req.tool_set.add(SetEmojiTool(ctx=self.ctx))
            for p in req.system_prompt:
                if p.name == "tools":
                    p.content += f"\n{self.emoji_react_prompt}"
                    break

        if self.send_likes_enabled:
            req.tool_set.add(SendQQLikesTool(ctx=self.ctx))
