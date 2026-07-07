from pydantic import BaseModel, EmailStr, Field, field_validator


def _check_bcrypt_len(v: str) -> str:
    # bcrypt 5.0 硬性拒绝超过 72 字节的密码（按 UTF-8 计），否则 hashpw/checkpw 抛 ValueError。
    if len(v.encode("utf-8")) > 72:
        raise ValueError("密码过长（最多 72 字节，约 24 个汉字）")
    return v


class RequestCodeIn(BaseModel):
    email: EmailStr


class RegisterIn(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6)
    password: str = Field(min_length=8, max_length=128)

    _check_password_len = field_validator("password")(_check_bcrypt_len)


class LoginIn(BaseModel):
    email: EmailStr
    password: str

    _check_password_len = field_validator("password")(_check_bcrypt_len)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MeOut(BaseModel):
    id: str
    email: EmailStr
    role: str
