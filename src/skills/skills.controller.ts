import { Body, Controller, Delete, Get, Param, Patch, Post, UseGuards } from '@nestjs/common';
import { SupabaseAuthGuard } from '../auth/supabase-auth.guard.js';
import { CreateSkillDto } from './dto/create-skill.dto.js';
import { UpdateSkillDto } from './dto/update-skill.dto.js';
import { Skill, SkillsService } from './skills.service.js';

@Controller('skills')
export class SkillsController {
  constructor(private readonly skillsService: SkillsService) {}

  @Get()
  findAll(): Promise<Skill[]> {
    return this.skillsService.findAll();
  }

  @UseGuards(SupabaseAuthGuard)
  @Post()
  create(@Body() dto: CreateSkillDto): Promise<Skill> {
    return this.skillsService.create(dto);
  }

  @UseGuards(SupabaseAuthGuard)
  @Patch(':id')
  update(@Param('id') id: string, @Body() dto: UpdateSkillDto): Promise<Skill> {
    return this.skillsService.update(id, dto);
  }

  @UseGuards(SupabaseAuthGuard)
  @Delete(':id')
  remove(@Param('id') id: string): Promise<void> {
    return this.skillsService.remove(id);
  }
}
