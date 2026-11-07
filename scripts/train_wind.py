"""
CLI script to train and benchmark wind power forecasting models.
"""

import argparse
import sys

from smarthack.wind.training import train_and_benchmark


def main() -> int:
    """
    Execute CLI wind model training and benchmarking pipeline.

    :returns: Process exit code.
    """
    parser = argparse.ArgumentParser(description="Train and Benchmark Wind Power Forecasting Models")
    parser.add_argument(
        "--data-dir", type=str, default="data/wind", help="Directory with location CSVs"
    )
    parser.add_argument(
        "--models-dir", type=str, default="models/wind", help="Directory to save models"
    )
    parser.add_argument(
        "--train-until", type=str, default="2021-01-01", help="Train/test temporal split date"
    )
    args = parser.parse_args()

    print(f"\nStarting wind model training from '{args.data_dir}'...")
    try:
        results = train_and_benchmark(
            data_dir=args.data_dir,
            models_dir=args.models_dir,
            train_until=args.train_until,
        )
    except Exception as exc:
        print(f"Error during model training: {exc}", file=sys.stderr)
        return 1

    print("\nTraining complete! Best model:", results["best_model"])
    print(f"Holdout RMSE: {results['best_rmse']}, R2: {results['best_r2']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
