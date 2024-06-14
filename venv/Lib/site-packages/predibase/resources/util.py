from typing import Tuple


def parse_connection_and_dataset_name(s: str) -> Tuple[str, str]:
    segments = s.split("/")
    if len(segments) == 2:
        connection, name = segments
    elif len(segments) == 1:
        connection = "file_uploads"
        name = segments[0]
    else:
        raise ValueError(
            f"Got invalid dataset reference {s} - expected either <dataset_name> or "
            f"<connection_name>/<dataset_name>"
        )

    return connection, name
