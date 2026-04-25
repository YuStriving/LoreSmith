package com.ainovel.platform.interfaces.dto;

public record WorkspaceAssistantStreamResponse(
        String storyId,
        String messageId,
        String content,
        boolean fallbackUsed
) {}
