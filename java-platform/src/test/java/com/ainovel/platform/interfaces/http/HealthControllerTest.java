package com.ainovel.platform.interfaces.http;

import com.ainovel.platform.interfaces.dto.ApiResponse;
import com.ainovel.platform.interfaces.dto.HealthResponse;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class HealthControllerTest {
    @Test
    void healthReturnsOkEnvelope() {
        HealthController controller = new HealthController();
        ApiResponse<HealthResponse> response = controller.health();

        assertThat(response.code()).isEqualTo("OK");
        assertThat(response.data().status()).isEqualTo("ok");
        assertThat(response.data().service()).isEqualTo("java-platform");
    }
}
