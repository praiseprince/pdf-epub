import {
  AuthError,
  InvalidRequestError,
  JobFailedError,
  NetworkError,
  PollTimeoutError,
  RateLimitError,
  RequestTimeoutError,
  ResponseFormatError,
  ResultParseError,
  ServiceUnavailableError
} from "@paddleocr/api-sdk";

export type PublicPaddleError = {
  message: string;
  status: number;
  retryable: boolean;
};

export function toPublicPaddleError(error: unknown): PublicPaddleError {
  if (error instanceof AuthError) {
    return {
      message: "PaddleOCR authentication failed.",
      status: 502,
      retryable: false
    };
  }

  if (error instanceof InvalidRequestError) {
    return {
      message: "PaddleOCR rejected this PDF.",
      status: 400,
      retryable: false
    };
  }

  if (error instanceof RateLimitError) {
    const text = error.message.toLowerCase();
    return {
      message: text.includes("quota")
        ? "PaddleOCR free quota appears to be exhausted."
        : "PaddleOCR is rate limiting requests.",
      status: 429,
      retryable: !text.includes("quota")
    };
  }

  if (error instanceof ServiceUnavailableError || error instanceof NetworkError) {
    return {
      message: "PaddleOCR is temporarily unavailable.",
      status: 503,
      retryable: true
    };
  }

  if (error instanceof RequestTimeoutError || error instanceof PollTimeoutError) {
    return {
      message: "PaddleOCR request timed out.",
      status: 504,
      retryable: true
    };
  }

  if (error instanceof JobFailedError) {
    return {
      message: "Document parsing failed.",
      status: 502,
      retryable: false
    };
  }

  if (error instanceof ResponseFormatError || error instanceof ResultParseError) {
    return {
      message: "PaddleOCR returned a malformed response.",
      status: 502,
      retryable: false
    };
  }

  return {
    message: "Document parsing failed.",
    status: 502,
    retryable: false
  };
}

