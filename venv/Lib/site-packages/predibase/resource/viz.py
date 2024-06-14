import enum


class VisualizeType(enum.Enum):
    CONFUSION_MATRIX = "confusion_matrix"
    ROC_CURVES_FROM_TEST_STATISTICS = "roc_curves_from_test_statistics"
    FREQUENCY_VS_F1 = "frequency_vs_f1"
