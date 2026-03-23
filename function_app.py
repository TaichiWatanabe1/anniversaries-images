import logging
import os
from io import BytesIO


import azure.functions as func
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContentSettings
from google import genai
from google.genai import types
from PIL import Image

from anniversaries import fetch_anniversaries, get_today_mmdd, get_today_date

app = func.FunctionApp()


def _get_required_setting(name: str, *, fallback: str | None = None) -> str:
    """Return a non-empty app setting value, raising a clear error if missing."""
    candidates = [name]
    if fallback:
        candidates.append(fallback)

    for key in candidates:
        value = os.environ.get(key)
        if value and value.strip():
            if key != name:
                logging.info("Using app setting '%s' from fallback '%s'.", name, key)
            return value

    fallback_msg = f" (fallback: {fallback})" if fallback else ""
    raise RuntimeError(
        f"Missing required app setting: {name}{fallback_msg}. "
        "Please configure it in Azure Function App settings."
    )


def _create_blob_service_client() -> BlobServiceClient:
    """Create blob client from a valid connection string or managed identity."""
    for key in ("PUBLIC_BLOB_CONNECTION_STRING", "AzureWebJobsStorage"):
        raw_value = os.environ.get(key)
        if not raw_value or not raw_value.strip():
            continue

        conn_str = raw_value.strip()
        if conn_str == "UseDevelopmentStorage=true":
            raise RuntimeError(
                f"App setting '{key}' is set to UseDevelopmentStorage=true, "
                "which is only for local Azurite. Set a real Azure Storage "
                "connection string in Azure."
            )
        if conn_str.startswith("@Microsoft.KeyVault("):
            raise RuntimeError(
                f"App setting '{key}' contains an unresolved Key Vault reference. "
                "Check managed identity permissions and key vault reference status."
            )

        try:
            logging.info("Using blob connection string from app setting '%s'.", key)
            return BlobServiceClient.from_connection_string(conn_str)
        except ValueError as exc:
            raise RuntimeError(
                f"App setting '{key}' is present but malformed for Azure Storage "
                "connection string format."
            ) from exc

    account_url = os.environ.get("PUBLIC_BLOB_ACCOUNT_URL", "").strip()
    if account_url:
        logging.info(
            "Using blob account URL from PUBLIC_BLOB_ACCOUNT_URL with managed identity."
        )
        return BlobServiceClient(
            account_url=account_url, credential=DefaultAzureCredential()
        )

    raise RuntimeError(
        "Missing blob storage configuration. Set PUBLIC_BLOB_CONNECTION_STRING "
        "(or AzureWebJobsStorage), or set PUBLIC_BLOB_ACCOUNT_URL and grant the "
        "Function App managed identity 'Storage Blob Data Contributor'."
    )


def _extract_image_data(image_part) -> tuple[bytes, str | None]:
    """Extract inline image bytes and mime type from a Gemini response part."""
    inline_data = getattr(image_part, "inline_data", None)
    if inline_data is None:
        raise RuntimeError("Image part does not include inline_data.")

    data = getattr(inline_data, "data", None)
    if not isinstance(data, (bytes, bytearray)):
        raise RuntimeError("Image inline_data.data is missing or not bytes.")

    mime_type = getattr(inline_data, "mime_type", None)
    return bytes(data), mime_type


@app.timer_trigger(
    schedule="0 0 15 * * *",  # 毎日 15:00 UTC = 00:00 JST
    arg_name="myTimer",
    run_on_startup=False,
    use_monitor=False,
)
def generate_anniversary_image(myTimer: func.TimerRequest) -> None:
    try:
        logging.info("Anniversary image generation started.")

        gemini_api_key = _get_required_setting("GEMINI_API_KEY")
        blob_container_name = os.environ.get("BLOB_CONTAINER_NAME", "output")
        base_image_blob_name = os.environ.get("BASE_IMAGE_BLOB_NAME", "favicon.png")

        public_blob_client = _create_blob_service_client()
        base_image_blob = public_blob_client.get_blob_client(
            container=blob_container_name, blob=base_image_blob_name
        )
        base_image = Image.open(BytesIO(base_image_blob.download_blob().readall()))

        yymmdd = get_today_date()
        mmdd = get_today_mmdd()
        items = fetch_anniversaries(mmdd)

        client = genai.Client(api_key=gemini_api_key)
        if not items:
            logging.warning("No anniversaries found for mmdd=%s. No image will be generated.", mmdd)
            return

        container_client = public_blob_client.get_container_client(blob_container_name)
        blob_prefix = "anniversary_icon_"
        for blob in container_client.list_blobs(name_starts_with=blob_prefix):
            if blob.name.endswith(".png"):
                container_client.delete_blob(blob.name)
                logging.info("Deleted existing blob: %s/%s", blob_container_name, blob.name)

        for index, item in enumerate(items):
            prompt = f"""
            添付のアプリケーションのアイコンを**今日の情報**を元にアプリケーションのアイコンの中を装飾してください。
            今日が何の日かがわかるように、アプリケーションのアイコンの中に日付と記念日を入れてください。
            ただし、添付のアプリケーションのアイコンの外側は一切拡張しないでください。

            # 今日の情報
            - 日付: {yymmdd}
            - 記念日: {item}

            """

            response = client.models.generate_content(
                model="gemini-3.1-flash-image-preview",
                contents=[base_image, prompt],
                config=types.GenerateContentConfig(
                    response_modalities=["Image"],
                    image_config=types.ImageConfig(
                        aspect_ratio="1:1",
                        image_size="2K",
                    ),
                ),
            )

            image_part = None
            for part in response.parts:
                if getattr(part, "inline_data", None) is not None:
                    image_part = part
                elif getattr(part, "text", None):
                    logging.info(part.text)

            if image_part is None:
                raise RuntimeError("画像が返ってきませんでした。プロンプトや入力画像を見直してください。")

            image_data, mime_type = _extract_image_data(image_part)
            image_bytes = BytesIO(image_data)
            blob_name = f"anniversary_icon_{index}.png"
            logging.info(
                "Generated image for index=%d (%d bytes, mime=%s).", index, len(image_data), mime_type
            )

            blob_client = public_blob_client.get_blob_client(
                container=blob_container_name, blob=blob_name
            )
            upload_kwargs = {"overwrite": True}
            if mime_type:
                upload_kwargs["content_settings"] = ContentSettings(content_type=mime_type)
            blob_client.upload_blob(image_bytes, **upload_kwargs)

            logging.info("Image saved to blob: %s/%s", blob_container_name, blob_name)
    except Exception:
        logging.exception("Anniversary image generation failed.")
        raise
