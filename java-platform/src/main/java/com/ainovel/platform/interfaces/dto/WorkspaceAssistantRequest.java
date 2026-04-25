package com.ainovel.platform.interfaces.dto;

import jakarta.validation.constraints.NotBlank;

public record WorkspaceAssistantRequest(
        @NotBlank(message = "action is required") String action,
        String instruction
) {}
