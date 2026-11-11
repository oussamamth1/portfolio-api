import { Body, Controller, Delete, Get, Param, Patch, Post, UseGuards } from '@nestjs/common';
import { SupabaseAuthGuard } from '../auth/supabase-auth.guard.js';
import { CreateProjectDto } from './dto/create-project.dto.js';
import { UpdateProjectDto } from './dto/update-project.dto.js';
import { Project, ProjectsService } from './projects.service.js';

@Controller('projects')
export class ProjectsController {
  constructor(private readonly projectsService: ProjectsService) {}

  @Get()
  findAll(): Promise<Project[]> {
    return this.projectsService.findAll();
  }

  @UseGuards(SupabaseAuthGuard)
  @Post()
  create(@Body() dto: CreateProjectDto): Promise<Project> {
    return this.projectsService.create(dto);
  }

  @UseGuards(SupabaseAuthGuard)
  @Patch(':id')
  update(@Param('id') id: string, @Body() dto: UpdateProjectDto): Promise<Project> {
    return this.projectsService.update(id, dto);
  }

  @UseGuards(SupabaseAuthGuard)
  @Delete(':id')
  remove(@Param('id') id: string): Promise<void> {
    return this.projectsService.remove(id);
  }
}
