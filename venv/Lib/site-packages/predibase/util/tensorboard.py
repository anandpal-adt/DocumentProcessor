from predibase.util.metrics import model_logs_directory


def launch_tensorboard(
    model_id: int,
) -> None:
    logs_dir_name = model_logs_directory(model_id)

    try:
        import tensorboard.notebook
    except ImportError:
        print("Tensorboard not installed. Install with `pip install tensorboard`")
        raise ImportError("Tensorboard not installed. Install with `pip install tensorboard`")

    # TODO: Detect if default port is in use and select another one.
    tensorboard.notebook.start(f"--logdir={logs_dir_name}")
