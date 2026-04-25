package com.ainovel.platform.interfaces.dto;

public record WorkspaceNodeResponse(
        String id,
        String parentId,
        String type,
        String title,
        Integer order,
        String summary
) {}
