from random_user_agent.params import HardwareType, Popularity, SoftwareType
from random_user_agent.user_agent import UserAgent

ua_rotator = UserAgent(
    software_types=[SoftwareType.WEB_BROWSER.value], hardware_types=[HardwareType.COMPUTER.value],
    popularity=[Popularity.POPULAR.value]
)
