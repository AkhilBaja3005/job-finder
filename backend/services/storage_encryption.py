import os
import hashlib
from typing import Optional, Union
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

# Master salt to scope user key derivations (can be overridden via environment)
STORAGE_SALT = os.getenv("STORAGE_ENCRYPTION_SALT", "job-finder-zero-knowledge-v1-salt").encode("utf-8")


def derive_user_key(user_token_or_id: Optional[str]) -> bytes:
    """
    Derives a deterministic 256-bit AES-GCM key scoped specifically to the user's
    authentication token / user_id.

    Zero-knowledge guarantee: Without the user's active session token, raw files
    stored on Hugging Face persistent volumes (/data) cannot be decrypted.
    """
    raw_id = (user_token_or_id or "guest-unscoped").strip().encode("utf-8")
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=STORAGE_SALT,
        info=b"user-storage-encryption-key-v1",
    )
    return hkdf.derive(raw_id)


def encrypt_data(data: Union[str, bytes], user_token_or_id: Optional[str]) -> bytes:
    """
    Encrypts plaintext bytes or string using AES-256-GCM with a user-scoped key.
    Prepends a fresh 12-byte cryptographic nonce to the ciphertext.
    """
    if isinstance(data, str):
        data_bytes = data.encode("utf-8")
    else:
        data_bytes = data

    key = derive_user_key(user_token_or_id)
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)  # Standard 96-bit nonce for AES-GCM
    ciphertext = aesgcm.encrypt(nonce, data_bytes, None)
    return nonce + ciphertext


def decrypt_data(encrypted_bytes: bytes, user_token_or_id: Optional[str]) -> bytes:
    """
    Decrypts AES-256-GCM ciphertext using the user-scoped key.
    Extracts the first 12 bytes as the nonce.
    """
    if len(encrypted_bytes) < 28:  # 12-byte nonce + 16-byte GCM tag
        raise ValueError("Invalid encrypted data payload: payload is too short.")

    nonce = encrypted_bytes[:12]
    ciphertext = encrypted_bytes[12:]
    key = derive_user_key(user_token_or_id)
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None)


def write_encrypted_file(file_path: str, data: Union[str, bytes], user_token_or_id: Optional[str]) -> str:
    """
    Writes data encrypted with AES-256-GCM to disk. Appends .enc extension if not already present.
    Returns the path of the encrypted file written.
    """
    enc_path = file_path if file_path.endswith(".enc") else f"{file_path}.enc"
    os.makedirs(os.path.dirname(os.path.abspath(enc_path)), exist_ok=True)
    encrypted_bytes = encrypt_data(data, user_token_or_id)
    with open(enc_path, "wb") as f:
        f.write(encrypted_bytes)
    return enc_path


def read_encrypted_file(file_path: str, user_token_or_id: Optional[str]) -> bytes:
    """
    Reads an encrypted file (.enc) and decrypts its contents into plaintext bytes in memory.
    Falls back gracefully if the unencrypted file still exists during migration.
    """
    enc_path = file_path if file_path.endswith(".enc") else f"{file_path}.enc"
    if os.path.exists(enc_path):
        with open(enc_path, "rb") as f:
            encrypted_bytes = f.read()
        return decrypt_data(encrypted_bytes, user_token_or_id)

    # Fallback for legacy unencrypted file
    if os.path.exists(file_path):
        with open(file_path, "rb") as f:
            return f.read()

    raise FileNotFoundError(f"Neither {enc_path} nor {file_path} exists.")
