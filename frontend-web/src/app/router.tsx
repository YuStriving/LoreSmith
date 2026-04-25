import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom'
import { AppShell } from '../components/layout/AppShell'
import { HomePage } from '../pages/HomePage'
import { StoriesPage } from '../pages/StoriesPage'
import { NewStoryPage } from '../pages/NewStoryPage'
import { ReadingPage } from '../pages/ReadingPage'
import { StoryWorkspacePage } from '../pages/StoryWorkspacePage'

const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <HomePage /> },
      { path: 'stories', element: <StoriesPage /> },
      { path: 'stories/new', element: <NewStoryPage /> },
      { path: 'stories/:storyId/workspace', element: <StoryWorkspacePage /> },
      { path: 'runs/:runId', element: <Navigate to='/stories' replace /> },
      { path: 'read', element: <ReadingPage /> },
      { path: '*', element: <Navigate to='/' replace /> },
    ],
  },
])

export function AppRouter() {
  return <RouterProvider router={router} />
}
