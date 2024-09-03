from pydantic import BaseModel
from typing import Optional

class ImageData(BaseModel):
    INVOICE_HEADER: str
    ADDRESS: str
    GST_NO: str
    ACCOUNT_NO: Optional[str] = None
    TOTAL_AMOUNT: str
    IMAGE_BASE64: str
    ID: str