from aiogram.dispatcher.handler import CancelHandler
from runtime.final_private_ui import start_keyboard


def install(app):
    dp=app.dp
    if getattr(app,"_private_start_guard_v2",False): return False
    app._private_start_guard_v2=True
    async def start(message):
        if message.chat.type!="private": return
        await message.answer("🎭 <b>Mafia Nights</b>\n\nیک گزینه را انتخاب کنید:",reply_markup=start_keyboard(),parse_mode="HTML")
        raise CancelHandler()
    dp.register_message_handler(start,commands=["start"],state="*")
    reg=getattr(getattr(dp,"message_handlers",None),"handlers",[])
    for i,item in enumerate(reg):
        if getattr(item,"handler",None) is start:
            reg.insert(0,reg.pop(i)); break
    return True
