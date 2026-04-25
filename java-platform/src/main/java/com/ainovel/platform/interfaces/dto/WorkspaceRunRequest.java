package com.ainovel.platform.interfaces.dto;

public record WorkspaceRunRequest(
        String prompt,
        String provider,
        String model,
        String configPath
) {}
