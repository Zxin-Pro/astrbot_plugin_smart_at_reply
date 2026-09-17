import logging

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import At, Plain

logger = logging.getLogger("SmartAtReply")

# 被 @ 时的默认回复内容（可在配置 reply_text 中覆盖）
DEFAULT_REPLY_TEXT = "你好，有什么可以帮你的吗？"


@register("SmartAtReply", "Zxin-Pro", "根据是否被@决定回复是否带@", "1.0.0")
class SmartAtReply(Star):
    """
    SmartAtReply 插件
    =================
    功能：根据用户消息中是否 @ 了机器人，决定机器人回复时是否 @ 发送者。

    逻辑：
    1. 群聊中用户 @ 了机器人 -> 回复开头先 @ 发送者，再发送文本内容；
    2. 未被 @ -> 不拦截消息，走 AstrBot 正常回复流程（纯文本，不带 @）；
       （如希望未被 @ 时也由本插件直接回复纯文本，见 on_all_message 内注释）
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
    # 消息监听
    # ------------------------------------------------------------------
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_all_message(self, event: AstrMessageEvent):
        """监听所有消息（群聊 + 私聊），根据是否被 @ 决定回复形式"""
        try:
            self_id = str(event.message_obj.self_id)
            sender_id = str(event.get_sender_id() or "")

            # 防止机器人响应自己发出的消息造成死循环
            if not sender_id or sender_id == self_id:
                return

            # 私聊没有 @ 的概念，视为"已提及"（直聊即对话）
            is_private = not event.get_group_id()
            mentioned = is_private or self._is_bot_mentioned(event)

            if not mentioned:
                # only_reply_when_mentioned = true：未被 @ 直接拦截，不再回复
                if self._get_config("only_reply_when_mentioned", False):
                    event.stop_event()
                    return
                # 未被 @：不拦截，走正常回复流程（回复自然不带 @）
                # 如希望未被 @ 时也由本插件回复纯文本，取消下面两行注释：
                # reply_text = self._get_config("reply_text", DEFAULT_REPLY_TEXT)
                # yield event.plain_result(reply_text)
                return

            reply_text = self._get_config("reply_text", DEFAULT_REPLY_TEXT)

            if is_private:
                # 私聊回复 @ 无意义，直接纯文本
                yield event.plain_result(reply_text)
                return

            # 被 @ 了：回复开头先 @ 发送者，再发送文本内容
            yield event.chain_result([
                At(qq=event.get_sender_id()),   # 开头 @ 发送者
                Plain(" " + reply_text),        # @ 后补一个空格更自然
            ])
        except Exception as e:
            # 监听器内异常兜底，不影响 AstrBot 主流程
            logger.error(f"[SmartAtReply] 处理消息异常: {e}")
