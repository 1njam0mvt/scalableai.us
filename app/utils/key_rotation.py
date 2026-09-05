from typing import Optional, Tuple

def get_next_key_pair(num_keys: int,need_brain: bool = True) -> Tuple[Optional[int], int]:

    if not need_brain:
        return (None, 0)

    if num_keys <= 1:
        return (0, 0)    

    return (0, 1)    
    