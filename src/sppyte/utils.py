import os


def get_hostname():
    if "COMPUTERNAME" in os.environ:
        return os.environ["COMPUTERNAME"]
    else:
        return os.uname()[1]  # For Unix-like systems


def parse_auth_token(response):
    pass


def parse_form_digest(response):
    pass


def parse_item_type(response):
    pass
