import { Module } from '@nestjs/common';
import { InternshipsController } from './internships.controller.js';
import { InternshipsService } from './internships.service.js';

@Module({
  controllers: [InternshipsController],
  providers: [InternshipsService],
})
export class InternshipsModule {}
