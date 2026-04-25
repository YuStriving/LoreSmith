package com.ainovel.platform.interfaces.http;

import com.ainovel.platform.interfaces.dto.ErrorResponse;
import org.junit.jupiter.api.Test;
import org.springframework.http.ResponseEntity;

import static org.assertj.core.api.Assertions.assertThat;

class ApiExceptionHandlerTest {
    @Test
    void illegalArgumentReturnsBadRequest() {
        ApiExceptionHandler handler = new ApiExceptionHandler();
        ResponseEntity<ErrorResponse> response = handler.handleIllegalArgument(new IllegalArgumentException("bad input"));

        assertThat(response.getStatusCode().value()).isEqualTo(400);
        assertThat(response.getBody()).isNotNull();
        assertThat(response.getBody().code()).isEqualTo("INVALID_ARGUMENT");
        assertThat(response.getBody().message()).isEqualTo("bad input");
    }

    @Test
    void genericExceptionReturnsErrorResponse() {
        ApiExceptionHandler handler = new ApiExceptionHandler();
        ResponseEntity<ErrorResponse> response = handler.handleGeneric(new RuntimeException("boom"));

        assertThat(response.getStatusCode().value()).isEqualTo(502);
        assertThat(response.getBody()).isNotNull();
        assertThat(response.getBody().code()).isEqualTo("UPSTREAM_ERROR");
        assertThat(response.getBody().message()).isEqualTo("boom");
    }
}
