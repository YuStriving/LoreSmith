package com.ainovel.platform.interfaces.dto;

public record WorkspaceAssistantMessageResponse(
        String id,
        String role,
        String content,
        String createdAt
) {}
