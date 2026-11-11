import { Body, Controller, Delete, Get, Param, Patch, Post, UseGuards } from '@nestjs/common';
import { SupabaseAuthGuard } from '../auth/supabase-auth.guard.js';
import { CreateEducationDto } from './dto/create-education.dto.js';
import { UpdateEducationDto } from './dto/update-education.dto.js';
import { Education, EducationService } from './education.service.js';

@Controller('education')
export class EducationController {
  constructor(private readonly educationService: EducationService) {}

  @Get()
  findAll(): Promise<Education[]> {
    return this.educationService.findAll();
  }

  @UseGuards(SupabaseAuthGuard)
  @Post()
  create(@Body() dto: CreateEducationDto): Promise<Education> {
    return this.educationService.create(dto);
  }

  @UseGuards(SupabaseAuthGuard)
  @Patch(':id')
  update(@Param('id') id: string, @Body() dto: UpdateEducationDto): Promise<Education> {
    return this.educationService.update(id, dto);
  }

  @UseGuards(SupabaseAuthGuard)
  @Delete(':id')
  remove(@Param('id') id: string): Promise<void> {
    return this.educationService.remove(id);
  }
}
