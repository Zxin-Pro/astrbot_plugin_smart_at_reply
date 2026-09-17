import logging

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import At, Plain
from astrbot.core.message.message_event_result import MessageChain

logger = logging.getLogger("SmartAtReply")


@register("SmartAtReply", "Zxin-Pro", "根据是否被@决定回复是否带@", "1.1.0")
class SmartAtReply(Star):
    """
    SmartAtReply 插件
    =================
    功能：根据用户消息中是否 @ 了机器人，决定机器人回复时是否 @ 发送者。

    逻辑：
    1. 群聊中用户 @ 了机器人 -> 正常响应（走 LLM 等），但回复开头先 @ 发送者，再发送文本内容；
    2. 未被 @ -> 正常响应，回复为纯文本，不带 @；
    3. only_reply_when_mentioned = true 时，未被 @ 的消息直接拦截，不再回复。
    """

    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        # config 由 AstrBot 自动注入（需插件目录提供 _conf_schema.json）
        # 未提供 schema 时 config 为 None，所有配置项走默认值
        self.config = config if isinstance(config, dict) else {}

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    def _is_bot_mentioned(self, event: AstrMessageEvent) -> bool:
        """判断本条消息中是否 @ 了机器人"""
        bot_id = event.message_obj.self_id
        for seg in event.message_obj.message:
            # At 组件的 qq 属性即被 @ 人的 QQ 号，统一转字符串比较
            if isinstance(seg, At) and str(seg.qq) == str(bot_id):
                return True
        return False

    def _get_config(self, key: str, default):
        """安全读取配置项，配置未注入时返回默认值"""
        try:
            value = self.config.get(key, default)
        except Exception:
            return default
        return default if value is None else value

    # ------------------------------------------------------------------
    # 消息监听：负责 only_reply_when_mentioned 拦截
    # ------------------------------------------------------------------
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_all_message(self, event: AstrMessageEvent):
        """监听所有消息（群聊 + 私聊），未被 @ 且开启拦截时直接停止响应"""
        try:
            self_id = str(event.message_obj.self_id)
            sender_id = str(event.get_sender_id() or "")

            # 防止机器人响应自己发出的消息造成死循环
            if not sender_id or sender_id == self_id:
                return

            # 私聊没有 @ 的概念，视为"已提及"（直聊即对话）
            is_private = not event.get_group_id()
            mentioned = is_private or self._is_bot_mentioned(event)

            if not mentioned and self._get_config("only_reply_when_mentioned", False):
                # 仅在被 @ 时才响应：未被 @ 直接拦截，不再回复
                event.stop_event()
        except Exception as e:
            # 监听器内异常兜底，不影响 AstrBot 主流程
            logger.error(f"[SmartAtReply] on_all_message 异常: {e}")

    # ------------------------------------------------------------------
    # LLM 响应钩子：被 @ 时在回复开头插入 @ 发送者
    # ------------------------------------------------------------------
    @filter.on_llm_response()
    async def on_llm_response(self, event: AstrMessageEvent, resp):
        """
        源码核实（tool_loop_agent_runner.py / internal.py）：
        OnLLMResponseEvent 在 on_agent_done 时触发，之后才用 final_llm_resp 组装
        发送链（优先 result_chain，其次 completion_text），所以在钩子里往
        resp.result_chain 开头插 At 组件即可实现"回复第一句 @ 发送者"。
        """
        try:
            # 私聊回复 @ 无意义，跳过
            if not event.get_group_id():
                return

            # 只处理本条消息确实 @ 了机器人的情况
            if not self._is_bot_mentioned(event):
                return

            sender_id = event.get_sender_id()
            at_seg = At(qq=sender_id)
            space_seg = Plain(" ")

            if resp.result_chain is not None and getattr(resp.result_chain, "chain", None):
                # 已有响应链：直接在开头插入 @ + 空格
                resp.result_chain.chain.insert(0, space_seg)
                resp.result_chain.chain.insert(0, at_seg)
            else:
                # 响应链为空：用 completion_text 构建链再插入 @
                text = resp.completion_text or ""
                if not text:
                    return
                chain = MessageChain().message(text)
                chain.chain.insert(0, space_seg)
                chain.chain.insert(0, at_seg)
                resp.result_chain = chain
        except Exception as e:
            logger.error(f"[SmartAtReply] on_llm_response 异常: {e}")
