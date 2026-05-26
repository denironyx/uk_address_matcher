old_blocking_rules = [
    (
        "l.postcode = r.postcode and ((l.numeric_token_1 = r.numeric_token_1) "
        "or (l.numeric_token_2 = r.numeric_token_2))"
    ),
    (
        "l.postcode = r.postcode and ((l.numeric_token_2 = r.numeric_token_1) "
        "or (l.numeric_token_1 = r.numeric_token_2))"
    ),
    (
        "l.numeric_token_1 = list_extract(r.very_unusual_tokens_arr, 1) "
        "and l.postcode = r.postcode"
    ),
]
