from aiogram.fsm.state import State, StatesGroup


class ApplicationForm(StatesGroup):
    name = State()
    age = State()
    referral = State()
    expectations = State()
    bio = State()
    interview = State()


class TicketForm(StatesGroup):
    active = State()


class ModeratorReply(StatesGroup):
    ticket_message = State()
    rejection_reason = State()


class ProfileEdit(StatesGroup):
    name = State()
    age = State()
    hobbies = State()
    bio = State()
    avatar = State()
    video_avatar = State()
    custom_status = State()


class CookiePurchase(StatesGroup):
    receipt = State()


class FlexiblePurchase(StatesGroup):
    amount = State()


class PetFlow(StatesGroup):
    name = State()
    rename = State()


class MailboxForm(StatesGroup):
    text = State()


class GiftFlow(StatesGroup):
    target = State()


class ShopAdminFlow(StatesGroup):
    category_title = State()
    category_intro = State()
    item_title = State()
    item_description = State()
    item_price = State()
    item_image = State()
    header_title = State()
    header_text = State()
    cookie_rate = State()
    cookie_title = State()
    cookie_intro = State()
    cookie_button = State()
    cookie_packs = State()
    edit_value = State()


class AdminFlow(StatesGroup):
    user_value = State()
    broadcast_private = State()
    post_pick = State()
    post_body = State()
    post_media = State()
    post_buttons = State()
    post_poll_ask = State()
    post_poll_question = State()
    post_poll_options = State()
    post_rsvp_ask = State()
    post_preview = State()
    post_pay_ask = State()
    post_pay_text = State()
    post_pay_price = State()
    contest_text = State()
    contest_media = State()
    contest_prize = State()
    mention_all = State()
    automessage_content = State()
    automessage_interval = State()
    role_name = State()
    role_rename = State()
