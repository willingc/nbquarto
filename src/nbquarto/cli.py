import argparse
import logging
from pathlib import Path, PurePosixPath

import yaml

from .processor import NotebookProcessor


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def get_configuration(config_file: str):
    """
    Get the configuration from a yaml file and verifies
    all imports are valid.

    Args:
        config_file (`str`):
            The path to the configuration file that should be used.
    """
    with open(config_file, "r") as f:
        config = yaml.safe_load(f)
    processor_imports = config.get("imports", [])

    problematic_imports = []
    for processor_import in processor_imports:
        logging.debug(f"Attempting to import {processor_import}")
        module_location, class_name = processor_import.split(":")
        module = __import__(module_location, fromlist=[class_name])
        try:
            getattr(module, class_name)
        except AttributeError:
            problematic_imports.append(processor_import)
    if len(problematic_imports) > 0:
        logging.debug("Some imports were unsuccessful")
        problematic_imports = "\n".join([f"- {problematic_import}" for problematic_import in problematic_imports])
        raise ImportError(f"Could not import the following processors:\n    {problematic_imports}")
    else:
        logger.debug("All imports were successful")
    return config


def process_notebook(notebook_location: str, config_file: str, output_folder: str = None):
    """
    Apply a set of processors defined in the `config_file` to
    a notebook at `notebook_location`

    Args:
        notebook_location (`str`):
            The path to the notebook that should be processed
        config_file (`str`):
            The path to the configuration file that should be used.
    """
    config = get_configuration(config_file)

    # Bring in the processors
    logger.debug("Importing processors")
    processors = config.get("processors", [])
    for i, processor in enumerate(processors):
        module_location, class_name = processor.split(":")
        module = __import__(module_location, fromlist=[class_name])
        processors[i] = getattr(module, class_name)

    # Process and save the new notebook
    logger.debug(f"Processing notebook {notebook_location} with processors: {processors}")
    notebook_processor = NotebookProcessor(notebook_location, processors=processors, config=config)
    notebook_processor.process_notebook()
    if output_folder is None:
        if "output_folder" not in config:
            logger.warn(
                "No output location was specified in the config file. Saving to the `processed` folder in the same directory."
            )
            output_folder = "processed"
        else:
            output_folder = config.get("output_folder")
    documentation_source = config.get("documentation_source", "nbs")
    output_folder = PurePosixPath(output_folder)
    notebook_location = PurePosixPath(notebook_location)

    output_location = output_folder / notebook_location.relative_to(documentation_source)
    Path(output_location.parent).mkdir(parents=True, exist_ok=True)

    # Convert notebook to `qmd`
    notebook = notebook_processor.notebook

    # Initialize the markdown string
    md = []

    # For each cell in the notebook
    for i, cell in enumerate(notebook["cells"]):
        if i == 0 and cell["cell_type"] == "markdown":
            # If the first cell is markdown, it's probably the title
            # so add it to the markdown string
            content = cell["source"].split("\n")
            title = content[0]
            # Generate quarto metadata
            md.append(f'---\ntitle: {title.replace("#", "").lstrip().rstrip()}\njupyter: python3\n---\n')
            md.append("\n".join(content[1:]))
            # Add a newline to separate cells
            md.append("\n")

        # Depending on the cell's type, handle it differently
        elif cell["cell_type"] in ("markdown", "raw"):
            md.extend(cell["source"].split("\n"))

        elif cell["cell_type"] == "code":
            # Add code wrapped in triple backticks and curly braces
            md.append("```{python}")
            md.extend(cell["source"].split("\n"))
            md.append("```")

        else:
            raise ValueError(f"Unexpected cell type {cell['cell_type']}")

    # Join the markdown lines into a single string
    md_source = "\n".join(md)
    output_location = output_location.with_suffix(".qmd")

    with open(output_location, "w") as f:
        f.write(md_source)
    logger.info(f"Successfully processed notebook at {notebook_location} and saved to {output_location}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config_file",
        type=str,
        help="The path to the configuration file that should be used which contains the processors to be applied.",
    )
    notebook_group = parser.add_mutually_exclusive_group(required=True)
    notebook_group.add_argument(
        "--notebook_file",
        type=str,
        help="The path to the notebook that should be processed.",
    )
    notebook_group.add_argument(
        "--notebook_folder",
        type=str,
        help="The path to the folder containing the notebooks that should be processed.",
    )
    parser.add_argument(
        "--output_folder",
        type=str,
        default=None,
        help="The path to the folder where the processed notebooks should be saved, will use the one defined in `--config_file` if not passed.",
    )
    args = parser.parse_args()
    if args.notebook_folder is not None:
        for path in Path(args.notebook_folder).glob("**/*"):
            if path.is_file() and path.suffix == ".ipynb":
                process_notebook(path, args.config_file, args.output_folder)
    else:
        process_notebook(args.notebook_file, args.config_file, args.output_folder)
