def generate_username(user_dict : dict, full_name : str) -> str:
    username = full_name
    if full_name in user_dict:
        user_dict[full_name] += 1
        username += " (" + str(user_dict[full_name]) + ")"
    else:
        user_dict[full_name] = 0

    return username


