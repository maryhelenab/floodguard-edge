"""Create deployment ZIP files for the FloodGuard Lambda functions."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIRECTORY = Path(__file__).resolve().parent

LAMBDA_FUNCTIONS = {
    "floodguard-ingestion-lambda.zip": (
        PROJECT_ROOT / "backend" / "lambda_ingestion.py"
    ),
    "floodguard-query-lambda.zip": (
        PROJECT_ROOT / "backend" / "lambda_query.py"
    ),
}


def create_lambda_packages() -> None:
    """Create one deployment ZIP for each Lambda source file."""

    for zip_name, source_file in LAMBDA_FUNCTIONS.items():
        if not source_file.exists():
            raise FileNotFoundError(
                f"Lambda source file not found: {source_file}"
            )

        output_file = OUTPUT_DIRECTORY / zip_name

        with ZipFile(
            output_file,
            mode="w",
            compression=ZIP_DEFLATED,
        ) as archive:
            archive.write(
                source_file,
                arcname=source_file.name,
            )

        print(
            f"Created {output_file.relative_to(PROJECT_ROOT)} "
            f"from {source_file.relative_to(PROJECT_ROOT)}"
        )


if __name__ == "__main__":
    create_lambda_packages()
