package com.ainovel.platform.interfaces.dto;

public record RunInstructionRequest(
        String type,
        String text,
        String decision,
        String feedback
) {}
