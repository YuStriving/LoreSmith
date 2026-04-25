package com.ainovel.platform.interfaces.http;

import com.ainovel.platform.application.StoryApplicationService;
import com.ainovel.platform.interfaces.dto.ApiResponse;
import com.ainovel.platform.interfaces.dto.CreateStoryRequest;
import com.ainovel.platform.interfaces.dto.CreateStoryResponse;
import com.ainovel.platform.interfaces.dto.DeleteStoryResponse;
import com.ainovel.platform.interfaces.dto.StoryListResponse;
import com.ainovel.platform.interfaces.dto.StoryResponse;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/stories")
public class StoryController {
    private final StoryApplicationService storyService;

    public StoryController(StoryApplicationService storyService) {
        this.storyService = storyService;
    }

    @GetMapping
    public ApiResponse<StoryListResponse> list() {
        return ApiResponse.ok(storyService.listStories());
    }

    @GetMapping("/{storyId}")
    public ApiResponse<StoryResponse> get(@PathVariable String storyId) {
        return ApiResponse.ok(storyService.getStory(storyId));
    }

    @PostMapping
    public ApiResponse<CreateStoryResponse> create(@Valid @RequestBody CreateStoryRequest request) {
        return ApiResponse.ok(storyService.createStory(request));
    }

    @DeleteMapping("/{storyId}")
    public ApiResponse<DeleteStoryResponse> delete(@PathVariable String storyId) {
        return ApiResponse.ok(storyService.deleteStory(storyId));
    }
}
