"""Create the small ZIP files required to deploy the Lambda functions."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


# Resolve paths from this file so the script works from any current directory.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIRECTORY = Path(__file__).resolve().parent

# Each output archive contains one Lambda source file at the archive root.
LAMBDA_FUNCTIONS = {
    "floodguard-ingestion-lambda.zip": (
        PROJECT_ROOT / "backend" / "lambda_ingestion.py"
    ),
    "floodguard-query-lambda.zip": (
        PROJECT_ROOT / "backend" / "lambda_query.py"
    ),
}


def create_lambda_packages() -> None:
    """Create a fresh deployment archive for every configured Lambda."""

    for zip_name, source_file in LAMBDA_FUNCTIONS.items():
        # Fail early instead of creating an empty or incomplete deployment ZIP.
        if not source_file.exists():
            raise FileNotFoundError(
                f"Lambda source file not found: {source_file}"
            )

        output_file = OUTPUT_DIRECTORY / zip_name

        # Mode "w" replaces an old package so removed code is not retained.
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
    # This guard runs packaging only when the file is executed directly.
    create_lambda_packages()
