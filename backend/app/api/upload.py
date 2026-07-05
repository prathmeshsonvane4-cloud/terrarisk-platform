from fastapi import APIRouter, UploadFile, File

router = APIRouter(
    prefix="/upload",
    tags=["Portfolio Upload"],
)


@router.post("/csv")
async def upload_csv(file: UploadFile = File(...)):
    return {
        "success": True,
        "filename": file.filename,
        "content_type": file.content_type,
        "message": "Portfolio received successfully"
    }