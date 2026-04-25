package com.ainovel.platform.interfaces.dto;

public record UpdateWorkspaceNodeRequest(
        String title,
        String summary,
        String content
) {}
