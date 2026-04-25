package com.ainovel.platform.interfaces.dto;

import java.util.Map;

public record RunResponse(
        String runId,
        String storyId,
        String status,
        String kernelStatus,
        String phase,
        String flow,
        String provider,
        String model,
        Integer currentChapter,
        Integer completedCount,
        Integer totalWordCount,
        Map<String, Object> awaitingConfirmation
) {}
