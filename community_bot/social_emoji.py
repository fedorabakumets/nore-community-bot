import re

_MODIFIERS = re.compile(r"[\s\ufe0e\ufe0f🏻-🏿]")
_LIKE = re.compile(
    r"(?:[👩👨🧑]‍❤‍💋‍[👩👨🧑]|❤‍[🔥🩹]|[❤🩷🧡💛💚💙🩵💜🤎🖤🩶🤍♥♡❣💔💕💞💓💗💖💘💝💟🫶💌🥰😍😘😗😙😚😽💋💏])+"
)


def interaction_emoji(text: str) -> str | None:
    symbols = _MODIFIERS.sub("", text)
    if _LIKE.fullmatch(symbols):
        return "like"
    if symbols and symbols.strip("👍") == "":
        return "plus"
    if symbols and symbols.strip("👎") == "":
        return "minus"
    return None
