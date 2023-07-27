# Hey Emacs, this is -*- coding: utf-8; mode: python -*-

from collections.abc import Awaitable, Callable
from enum import Enum
from typing import (
    Any,
    Generic,
    Literal,
    Self,
    TypedDict,
    TypeVar,
    cast,
)


class RpcCodes(Enum):
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603


class RpcMessages(Enum):
    PARSE_ERROR = "Parse error"
    INVALID_REQUEST = "Invalid Request"
    METHOD_NOT_FOUND = "Method not found"
    INVALID_PARAMS = "Invalid params"
    INTERNAL_ERROR = "Internal error"


class RpcHandlerError(Exception):
    def __init__(
        self: Self,
        message: str,
        code: int,
        data: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.data = data


Buf = bytes

OnError = Callable[[Exception], None]
Listener = Callable[[Buf], Awaitable[None]]
Unsubscribe = Callable[[], Awaitable[Any]]
Subscribe = Callable[[Listener], Awaitable[Unsubscribe]]
Publish = Callable[[Buf], Awaitable[Any]]


class PubSub(TypedDict):
    subscribe: Subscribe
    publish: Publish


TypeReqParams = TypeVar("TypeReqParams", bound=TypedDict)


class ReqHead(TypedDict):
    method: str
    id: str


class Req(ReqHead):
    params: Any | None


class ReqWithParams(ReqHead, Generic[TypeReqParams]):
    params: TypeReqParams


TypeResData = TypeVar("TypeResData", bound=TypedDict)


class ResOkResultHead(TypedDict):
    type: Literal["ok"]


class ResOkResult(ResOkResultHead):
    data: Any | None


class ResOkResultWithData(ResOkResultHead, Generic[TypeResData]):
    data: TypeResData


class ResOkHead(TypedDict):
    id: str


class ResOk(ResOkHead):
    result: ResOkResult


class ResOkWithData(ResOkHead, Generic[TypeResData]):
    result: ResOkResultWithData[TypeResData]


class ResErrResultHead(TypedDict):
    type: Literal["err"]
    code: int
    message: str


class ResErrResult(ResErrResultHead):
    data: Any | None


class ResErrResultWithData(ResErrResultHead, Generic[TypeResData]):
    data: TypeResData


class ResErrHead(TypedDict):
    id: str


class ResErr(ResErrHead):
    result: ResErrResult


class ResErrWithData(ResErrHead, Generic[TypeResData]):
    result: ResErrResultWithData[TypeResData]


ReqHeadDecode = Callable[[Buf], ReqHead]

ReqDecode = Callable[[Buf], Req]
ResOkEncode = Callable[[ResOkWithData[Any]], Buf]
ResErrEncode = Callable[[ResErrWithData[Any]], Buf]


HandlerConverters = tuple[ReqDecode, ResOkEncode, ResErrEncode]


_ReqParams = Any
_ResData = Any
ReqHandler = Callable[[_ReqParams], Awaitable[_ResData]]


ReqMethodHandler = tuple[ReqHandler, HandlerConverters]


ReqHandlers = Callable[[Buf], Awaitable[None]]


ReqMethod = str


def make_rpc_req_handlers(
    req_methods: dict[ReqMethod, ReqMethodHandler],
    req_head_decode: ReqHeadDecode,
    publish: Publish,
    on_error: OnError | None = None,
) -> ReqHandlers:
    async def rpc_req_handlers(req_data: bytes) -> None:
        try:
            req_head = req_head_decode(req_data)
        except Exception as reason:
            if on_error:
                on_error(reason)
                return
            raise

        req_method = req_head["method"]
        req_id = req_head["id"]

        print("repose head ******************", req_head)

        handler, converters = req_methods[req_method]
        decode_req, encode_res_ok, encode_res_err = converters

        if req_method in req_methods:
            try:
                req = decode_req(req_data)
                params = (
                    cast(ReqWithParams[Any], req)["params"] if "params" in req else None
                )

                print("repose if ******************", params)
                data_ok = await handler(params)

                res_data = encode_res_ok(
                    {
                        "id": req_id,
                        "result": {
                            "type": "ok",
                            "data": data_ok,
                        },
                    },
                )

            except RpcHandlerError as reason:
                res_data = encode_res_err(
                    {
                        "id": req_id,
                        "result": {
                            "type": "err",
                            "code": reason.code,
                            "message": reason.message,
                            "data": reason.data,
                        },
                    },
                )

            except Exception:  # noqa: BLE001
                res_data = encode_res_err(
                    {
                        "id": req_id,
                        "result": {
                            "type": "err",
                            "code": RpcCodes.INTERNAL_ERROR.value,
                            "message": RpcMessages.INTERNAL_ERROR.value,
                            "data": None,
                        },
                    },
                )

        else:
            res_data = encode_res_err(
                {
                    "id": req_id,
                    "result": {
                        "type": "err",
                        "code": RpcCodes.METHOD_NOT_FOUND.value,
                        "message": RpcMessages.METHOD_NOT_FOUND.value,
                        "data": None,
                    },
                },
            )

        try:
            await publish(res_data)
        except Exception as cause:  # noqa: BLE001
            if on_error:
                on_error(cause)
            else:
                raise

    return rpc_req_handlers
