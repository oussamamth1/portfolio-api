import { Body, Controller, Delete, Get, Param, Patch, Post, UseGuards } from '@nestjs/common';
import { SupabaseAuthGuard } from '../auth/supabase-auth.guard.js';
import { Certification, CertificationsService } from './certifications.service.js';
import { CreateCertificationDto } from './dto/create-certification.dto.js';
import { UpdateCertificationDto } from './dto/update-certification.dto.js';

@Controller('certifications')
export class CertificationsController {
  constructor(private readonly certificationsService: CertificationsService) {}

  @Get()
  findAll(): Promise<Certification[]> {
    return this.certificationsService.findAll();
  }

  @UseGuards(SupabaseAuthGuard)
  @Post()
  create(@Body() dto: CreateCertificationDto): Promise<Certification> {
    return this.certificationsService.create(dto);
  }

  @UseGuards(SupabaseAuthGuard)
  @Patch(':id')
  update(@Param('id') id: string, @Body() dto: UpdateCertificationDto): Promise<Certification> {
    return this.certificationsService.update(id, dto);
  }

  @UseGuards(SupabaseAuthGuard)
  @Delete(':id')
  remove(@Param('id') id: string): Promise<void> {
    return this.certificationsService.remove(id);
  }
}
