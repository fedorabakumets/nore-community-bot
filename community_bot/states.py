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


class AdminFlow(StatesGroup):
    user_value = State()
    broadcast_private = State()
    post_community = State()
    mention_all = State()
    automessage_content = State()
    automessage_interval = State()
    role_name = State()
    role_rename = State()
