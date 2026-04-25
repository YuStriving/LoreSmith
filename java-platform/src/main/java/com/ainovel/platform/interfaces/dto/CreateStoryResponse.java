package com.ainovel.platform.interfaces.dto;

public record CreateStoryResponse(
        String storyId,
        String runId,
        String status,
        String kernelStatus
) {}
