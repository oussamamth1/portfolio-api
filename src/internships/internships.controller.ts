import { Body, Controller, Delete, Get, Param, Patch, Post, UseGuards } from '@nestjs/common';
import { SupabaseAuthGuard } from '../auth/supabase-auth.guard.js';
import { CreateInternshipDto } from './dto/create-internship.dto.js';
import { UpdateInternshipDto } from './dto/update-internship.dto.js';
import { Internship, InternshipsService } from './internships.service.js';

@Controller('internships')
export class InternshipsController {
  constructor(private readonly internshipsService: InternshipsService) {}

  @Get()
  findAll(): Promise<Internship[]> {
    return this.internshipsService.findAll();
  }

  @UseGuards(SupabaseAuthGuard)
  @Post()
  create(@Body() dto: CreateInternshipDto): Promise<Internship> {
    return this.internshipsService.create(dto);
  }

  @UseGuards(SupabaseAuthGuard)
  @Patch(':id')
  update(@Param('id') id: string, @Body() dto: UpdateInternshipDto): Promise<Internship> {
    return this.internshipsService.update(id, dto);
  }

  @UseGuards(SupabaseAuthGuard)
  @Delete(':id')
  remove(@Param('id') id: string): Promise<void> {
    return this.internshipsService.remove(id);
  }
}
