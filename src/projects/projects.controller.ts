import { Body, Controller, Delete, Get, Param, Patch, Post, UseGuards } from '@nestjs/common';
import type { User } from '@supabase/supabase-js';
import { CurrentUser } from '../auth/current-user.decorator.js';
import { SupabaseAuthGuard } from '../auth/supabase-auth.guard.js';
import { ProfileService } from '../profile/profile.service.js';
import { CreateProjectDto } from './dto/create-project.dto.js';
import { UpdateProjectDto } from './dto/update-project.dto.js';
import { Project, ProjectsService } from './projects.service.js';

@Controller()
export class ProjectsController {
  constructor(
    private readonly projectsService: ProjectsService,
    private readonly profileService: ProfileService,
  ) {}

  @Get('u/:username/projects')
  async findByUsername(@Param('username') username: string): Promise<Project[]> {
    const profile = await this.profileService.findByUsername(username);
    return this.projectsService.findAllFor(profile.user_id);
  }

  @UseGuards(SupabaseAuthGuard)
  @Get('me/projects')
  findOwn(@CurrentUser() user: User): Promise<Project[]> {
    return this.projectsService.findAllFor(user.id);
  }

  @UseGuards(SupabaseAuthGuard)
  @Post('me/projects')
  create(@CurrentUser() user: User, @Body() dto: CreateProjectDto): Promise<Project> {
    return this.projectsService.create(user.id, dto);
  }

  @UseGuards(SupabaseAuthGuard)
  @Patch('me/projects/:id')
  update(
    @CurrentUser() user: User,
    @Param('id') id: string,
    @Body() dto: UpdateProjectDto,
  ): Promise<Project> {
    return this.projectsService.update(user.id, id, dto);
  }

  @UseGuards(SupabaseAuthGuard)
  @Delete('me/projects/:id')
  remove(@CurrentUser() user: User, @Param('id') id: string): Promise<void> {
    return this.projectsService.remove(user.id, id);
  }
}
