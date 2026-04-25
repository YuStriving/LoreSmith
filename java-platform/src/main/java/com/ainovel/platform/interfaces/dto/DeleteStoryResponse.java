package com.ainovel.platform.interfaces.dto;

public record DeleteStoryResponse(
        String storyId,
        boolean deleted
) {}
