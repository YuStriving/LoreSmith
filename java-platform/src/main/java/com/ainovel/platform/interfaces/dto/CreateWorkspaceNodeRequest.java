package com.ainovel.platform.interfaces.dto;

import jakarta.validation.constraints.NotBlank;

public record CreateWorkspaceNodeRequest(
        String parentId,
        @NotBlank(message = "type is required") String type
) {}
