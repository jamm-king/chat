import httpx
from cryptography.fernet import InvalidToken
from sqlalchemy.exc import SQLAlchemyError

from app.adapters.outbound.persistence.models import get_connection
from app.adapters.outbound.notion.auth import decrypt_token
from app.adapters.outbound.notion.client import NotionApiError, NotionClient
from app.adapters.outbound.notion.loader import load_page
from app.domain.documents import TextDocument
from app.domain.errors import IngestionError, SourceError, StorageError


class NotionDocumentSource:
    def __init__(self, sessions, client: httpx.Client, encryption_key: str, api_version: str):
        self.sessions, self.client = sessions, client
        self.encryption_key, self.api_version = encryption_key, api_version

    def load(self, user_id, connection_id, page_id) -> TextDocument:
        try:
            with self.sessions() as session:
                connection = get_connection(session, user_id, connection_id)
                if connection is None:
                    raise IngestionError(404, "CONNECTION_NOT_FOUND", "Connection not found")
                token = decrypt_token(connection.access_token_encrypted, self.encryption_key)
            document = load_page(NotionClient(self.client, token, self.api_version), page_id)[0]
            return TextDocument(document.page_content, document.metadata)
        except NotionApiError as exc:
            raise SourceError(exc.code, str(exc), exc.status_code in {429, 502, 503, 504}) from None
        except InvalidToken:
            raise SourceError("INTERNAL_ERROR", "Stored credentials could not be read") from None
        except SQLAlchemyError:
            raise StorageError("Resource could not be stored") from None
